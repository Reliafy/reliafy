---
title: "Products and the items built from them"
task: "How do I keep a product's design (its structure, FME(C)A and parts list) and see what happens to every item built from it?"
category: "Maintenance strategy"
prerequisites: "Reliafy Maintenance, or the sample UAV product."
order: 28
# Reliafy Maintenance is operators-only for now: this guide is linked from the
# Products and Items pages and stays out of the index until Maintenance opens.
hidden: true
---

A **product** is something you design and build: a quadcopter, a pump skid, a
control panel. In Reliafy a product is its design: the **functional
structure** (what each part of it does, with its FME(C)A and RCM) and the
**part** it is, whose bill of materials is the product's parts list.

An **item** is one serial-numbered thing built from a product. Building an
item copies the product's functional structure into the item's own tree and
fits the item at its top, so each item keeps its own fitments, readings and
failure reports.

## Start with the sample

On **Products**, press **Add the sample UAV product**. It adds a small
inspection quadcopter (entirely invented): its design with a complete RCM
study and every failure mode scored, its part with a short bill of materials,
three items built from it, each with its flight hours and flights counted, a
motor replaced on one of them, two failure reports, and a flight-critical RBD
whose failure rates are placeholders.

## A product's page

A product's page is its design's tree, laid out like the asset tree on
**Assets**: the tree on the left, the panel about the row you pick on the
right. A design is not an operated thing, so nothing is done to it: its rows
have no failure reports, signals, stock, work or due dates. Its tabs:

- **Summary**: on the product's own row (the top of the tree), its facts
  (revision, part, positions, items built, open failure reports), then:
  - **Built items**: the items built from it, with **Build an item…**: give
    the serial and revision, check the positions it will make, then build.
  - **Failure reports on the built items**: every report on the items built
    from it, with the item and the place in the design. A report is filed on
    an item's own tree, not on the design.
  - **Bill of materials**: the parts list: the product's part and what it's
    made of, as designed, with the quantities rolled up (no stock: stock is
    kept for assets). **Change it…** opens the part's page.
  - **Analyses of this design**: the product's RBDs, **Make an RBD from this
    structure**, and a reliability prediction from its parts list.
- **RCM** and **FME(C)A**: the design's maintenance programme and its failure
  modes. The items built from it carry the programme out.

**Delete…** (in the product's row menu in its tree, or the bin on its row in
Products) deletes the design and everything inside it. Items built from it stay. Its
history stays, and **Undo** in the message that follows brings it back.

## Physical layout

A product has a physical layout as well as a functional structure: where each
part of it sits (the forward left arm, the battery bay). On the product's page,
switch the tree from **Positions** to **Locations** to see it.

- **New location inside** the product (the tree's last row) adds a place at the
  top of its layout; a location's row menu adds one inside it, renames, moves or
  deletes it.
- To place a position, open its full page and set its **Location** to one of
  the product's locations. The positions inside it are there too, unless they
  say otherwise. The ones not placed yet are listed last.
- Deleting a location keeps the positions placed there: they just have no
  place in the layout until you give them one.

A product's locations are part of its design, never assets: they don't show on
**Assets**. An item built from the product carries a copy of the layout, its
positions placed the same way. The copy is wherever the item is kept, and moves
with it.

The sample quadcopter's layout has four arms (each with its arm structure,
motor, speed controller and propeller), the centre body with its battery bay,
and the payload bay.

## Items

**Items** lists every serial-numbered thing, built from a product or not,
with its product, type, where it is and its open failure reports. Filter by
product or type, or search by name, serial or part number.

## Not yet

Applying a change to the design to items already built, revisions beyond a
label, and variants come later.
