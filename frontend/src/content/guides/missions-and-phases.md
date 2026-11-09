---
title: "Missions and phases"
task: "How do I work out the chance a product completes each of its missions, with its phases' own conditions (temperature, load, speed) and the blocks each phase needs?"
category: "Maintenance strategy"
prerequisites: "A position (or a product's design) with an RBD, ideally one built from what's inside it."
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

Missions are flown on an RBD, so they belong to the **position** the RBD is on.
Open **Assets → Explorer** (or a product's page) and choose the **Missions**
tab. The tree stays in the first column; under each position with an RBD are
its missions, with:

- **Phases**: how many, and their names.
- **Length**: every phase added up, in the RBD's time unit. Each phase's row
  under the mission shows that phase's own length.
- **Completes**: the chance the mission completes, once worked out.
- **RBD**: the diagram it's flown on.

A position without an RBD says **No RBD yet**: choose **Build an RBD from
what's inside…** from its **⋯** menu. Any position can have missions, the ones
inside a product included. A position doesn't take the missions of the position
above it: a gimbal's own missions are flown on the gimbal's own RBD.

## Add a mission

On the position's **⋯** menu, choose **Add a mission**. It opens in the table
area, the tree kept beside it (on a phone it takes the screen, with **‹
Back**). Name it, then **Add a phase** for each stage, in order, with how long
it lasts. Use **↑** and **↓** to reorder and **×** to remove one. **Save**
keeps it on the RBD.

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

**Blocks needed in this phase.** Click a block to say this phase doesn't need
it. It's treated as working for the phase, but it still ages, and if it has
failed it stays failed for a later phase that needs it.

**Vote counts.** Where the RBD has a k-of-n vote, set how many inputs this phase
needs: 4 of 6 motors on take-off, 3 of 6 in the cruise.

**Show the RBD** draws the diagram with the blocks this phase doesn't need
faded.

## Calculate

**Calculate** works the mission out, saved or not. The answer comes first: the
chance the mission completes. Then, for each phase:

- **Completes**: the chance the mission gets through the phase once it has
  started it.
- **Still going**: the chance the mission is still going at the phase's end.
- **Weakest**: the block whose failures end the most missions in that phase,
  and its share of the phase's failures.

The parts age across the **whole** mission, not afresh in each phase: wear in a
hot climb stays with a motor for the rest of the flight. When a block's
covariates change between phases, its life carries on from where the last phase
left it (for an accelerated life model, by cumulative exposure: the wear done
at one stress counts at the next).

## In the tools

The same is in the API, the CLI and the Claude connector: `analyse
rbd_mission` works a mission out (or every mission on an RBD) and lists the
covariates its phases can set; `change rbd_mission` adds, changes and deletes
one. See also [Model a mission in phases](/guides/phased-missions) for the RBD
builder's own phased mission.
