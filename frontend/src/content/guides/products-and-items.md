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

On **Products**, press **Add the sample UAV product**. It adds a small survey
quadcopter (entirely invented): its design with every failure mode scored,
its part with a short bill of materials, three items built from it, a motor
replaced on one of them, two failure reports, and a flight-critical RBD whose
failure rates are placeholders.

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
  - **Analyses of this design**: the product's RBDs, **Make an RBD from this
    structure**, and a reliability prediction from its parts list.
- **RCM** and **FME(C)A**: the design's maintenance programme and its failure
  modes. The items built from it carry the programme out.
- **Parts**: the parts list. On the product's row, its part and what it's made
  of; on any row, the parts on the parts lists of the positions there and
  inside it. No stock: stock is kept for assets.
- **Classes**: the position classes used there and inside it; tick **Show all
  classes** for every class and the item classes.

## Items

**Items** lists every serial-numbered thing, built from a product or not,
with its product, type, where it is and its open failure reports. Filter by
product or type, or search by name, serial or part number.

## Not yet

Applying a change to the design to items already built, revisions beyond a
label, and variants come later.
