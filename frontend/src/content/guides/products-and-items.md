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

- **Functional structure**: the design's tree, with its RCM and FME(C)A tabs.
  No failure report is filed on a design: a report is about an item.
- **Parts list**: the product's part and what it's made of.
- **Items**: the items built from it, with **Build an item**: give the serial
  and revision, check the positions it will make, then build.
- **Failure reports**: every report on the items built from it, with the item
  and the place in the design.
- **Analysis**: the product's RBDs, and **Make an RBD from this structure**.

## Items

**Items** lists every serial-numbered thing, built from a product or not,
with its product, type, where it is and its open failure reports. Filter by
product or type, or search by name, serial or part number.

## Not yet

Applying a change to the design to items already built, revisions beyond a
label, and variants come later.
