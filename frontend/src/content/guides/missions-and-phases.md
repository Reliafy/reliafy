---
title: "Missions and phases"
task: "How do I work out the chance a product completes each of its missions, with its phases' own conditions (temperature, load, speed) and the blocks each phase needs?"
category: "Maintenance strategy"
prerequisites: "A position (or a product's design) with positions inside it, or an RBD of its own."
order: 29
# Reliafy Maintenance is operators-only for now: this guide is linked from the
# Missions tab itself and stays out of the index until Maintenance opens.
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
the **Missions** tab. The tree stays in the first column; under each position
are its missions, with:

- **Phases**: how many, and their names.
- **Length**: every phase added up, in the RBD's time unit. Each phase's row
  under the mission shows that phase's own length.
- **Completes**: the chance the mission completes, once worked out.
- **RBD**: the diagram it's flown on.

Any position with positions inside it, or with a model of its own, can have
missions, the ones
inside a product included. A position doesn't take the missions of the position
above it: a gimbal's own missions are flown on the gimbal's own RBD.

## Add a mission

On the position's **⋯** menu, choose **Add a mission**. A position with an RBD
of its own gives the mission a copy of it, wired as it is there: parallel
trains, standby and k-out-of-n stay as they are (a repairable RBD's repairs and
planned work are left out: a mission doesn't repair). Without one, Reliafy
builds the mission's RBD from what's inside the position, the same way
**Build an RBD from what's inside…** does: each block takes the model in use
at its position, and a position with none gets a placeholder block, flagged,
never a made-up figure. Positions marked as backing each other up (the position's
**Redundancy inside…**) are wired as redundancy. Where nothing says how the blocks are wired (no
connections and no redundancy sets), they go in series, and the mission says so
(**Check the wiring**) until you mark the sets or wire its RBD otherwise. It's saved once, named after the
position and the mission ("Pump station — Mission 1"). A position with nothing
inside and no RBD is a single block: the position's own model in use. A
position with nothing inside and no model can't have a mission yet: give it a
model on the **Modelling** tab first.

The answer says why it has no bound: a mission is worked out from each block's
model at its point values. A mission too large to work out exactly is
simulated, and the range shown (90%, two-sided) is the simulation's own precision.

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
- **Standby**: it's there but not running, so it neither ages nor fails in that
  phase. It counts as working if it was still working when the phase began, and
  its age carries on when it next runs. Switching over is taken as perfect, and
  a standby block's running time after it takes over within the phase isn't
  counted.
- **Not needed**: the phase works without it. Its clock keeps running, so if it
  fails then, a later phase that needs it finds it failed.

Change a cell in place; **Calculate** works the mission out with what's on
screen, and **Save** keeps it. A pump that runs by day and stands by at night,
with its partner the other way round, ages only half the mission.

Each mission's phases are rows under it in the tree, in order, each with its
place (**Phase 2 of 3**) and its own length. A mission's row
menu (right-click it, or press its **⋯**) starts with **Add a phase**: it adds
one at the end and opens the mission on it, ready for its name and duration. A
phase's row menu has **Open…** (the mission, on that phase), **Move earlier**,
**Move later** and **Delete…**.

## Open a phase

Open a phase (the **▸** beside its number) to set what's different about it.

**Covariates in this phase.** Every use and environment covariate the RBD's
blocks left open at their positions is listed here, grouped **Use** and
**Environment**, each with its unit. These come from blocks on covariate models
(an NSWC-11 record, an accelerated life model or a proportional-hazards model)
whose design covariates were fixed at the position. Under each covariate you
see which blocks it feeds.

- Type a value once for the phase: every block using that covariate takes it.
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
chance the mission completes. Then, for each phase:

- **Completes**: the chance the mission gets through the phase once it has
  started it.
- **Still going**: the chance the mission is still going at the phase's end.
- **Weakest**: the block whose failures end the most missions in that phase,
  and its share of the phase's failures.

### Blocks with no model

A position with no model becomes a **placeholder** block: a stand-in life, so
the diagram can be drawn, not a real figure. A mission that needs such a block
says so with its answer. It names the blocks, shows the chance with the
placeholders and the chance from the blocks with models alone, and never names
a placeholder the weakest block. The grid marks each one **Placeholder**, and
the Missions tab shows the result with "placeholders" beside it.

You choose what to do with them:

- **Give them a model**: open the mission's RBD and set each block's model.
- **Leave them out**: mark them **Not needed** in every phase, so the mission
  is worked out from the blocks with models.
- Or set one **Not needed** only in the phases that don't use it.

The parts age across the **whole** mission, not afresh in each phase: wear in a
hot climb stays with a motor for the rest of the flight (except while a part
stands by). The result's notes say what **Standby** and **Not needed** mean. When a block's
covariates change between phases, its life carries on from where the last phase
left it (for an accelerated life model, by cumulative exposure: the wear done
at one stress counts at the next).

## In the tools

The same is in the API, the CLI and the Claude connector: `analyse
rbd_mission` works a mission out (or every mission on an RBD) and lists the
covariates its phases can set; `change rbd_mission` adds, changes and deletes
one, with a phase's `standby` and `not_needed` blocks. See also [Model a mission in phases](/guides/phased-missions) for the RBD
builder's own phased mission.
