---
title: "When a part is superseded or going obsolete (Maintenance › Parts and stock)"
task: "A maker has replaced a part with a new part number, or told me it's going out of production. How do I record that, see where the old one is used, and make sure stock and parts lists use the new one?"
category: "Maintenance strategy"
prerequisites: "The old and the new part in the parts catalogue, and some positions whose parts lists or tasks name the old one."
order: 31
# Reliafy Maintenance is operators-only for now: this guide is linked from a
# part's page and a position's parts list, and stays out of the index until
# Maintenance opens.
hidden: true
---

Parts change. A maker moves a seal kit to a new part number, or sends a notice
that a module goes out of production in March. Reliafy keeps the **old part**,
because items made with it are still in service and its history stays true, and
lets you say **what replaces it**. Everything that counts or offers parts then
follows the link.

## What Reliafy does, and doesn't, know

- **Superseded**: the old part is replaced by a new part number for the same
  job. A part can be superseded by one that is itself superseded later, and the
  chain is followed (B replaces A, then C replaces B).
- **Interchangeable**: two parts either of which will do. It works both ways.
- **Going obsolete** (an end-of-life notice, a last-time-buy date) has no field
  of its own. Write it in the part's **Notes** (*Maker's end-of-life notice, last
  time buy 31 Mar 2027*). The
  last-time-buy quantity and the cost of the two routes aren't worked out for
  you: the **Spares** view (spares for the year) gives the
  failures to cover and the stock to hold, which are the inputs.

## Record that a part is superseded

The app shows the link but doesn't have a control that makes it. Make it with
the maintenance tool's **parts.link** action: the part, the part that replaces
it (**other_part_id**) and **relation: superseded_by**. For two parts that are
interchangeable leave the relation out (that is the default), or say
**interchangeable**. Ask the Reliafy agent in words, or run it from the API or
`reliafy maintenance parts.link`. A link made by mistake comes off with
**parts.unlink** and the same two parts.

A part can't supersede itself, and the new part must be in the catalogue and
not retired.

## What follows

Once the link is there:

- The old part's page says **Superseded by** and the new part number, as a link.
- A position's **Parts** list says **Superseded: use** the new part under the old
  one's name, with its stock, and lists the interchangeable alternatives.
- Adding a part to a parts list marks the old one **(superseded)** in the picker.
- A work order offers the new part first (*use instead of* the old one), then the
  old one marked *superseded*, then the alternatives, so a fitter picks the
  right one at the shelf.
- **Usable now** in the spares view counts the stock of the old part, the parts
  that supersede it and the ones interchangeable with it, in every store, as one
  stock. So stock of the old part still counts towards a part you've moved to,
  and a critical spare isn't flagged short while its replacement is on the
  shelf.

Nothing is rewritten for you. A task that names the old part as a spare still
names it, and a position's parts list still has it as its entry. Change those
yourself as below.

## Find where the old part is used

On the old part's page:

- **Items of it** says how many items of that part are in service.
- **Where used** lists the assemblies whose structure includes it, the positions
  whose parts lists name it, and where items of it are fitted.

For the tasks that call for it as a spare, open each position's **What it needs**
view. Its **Spares** column shows which tasks name the part. Change the part
under the task's **Spares**, then check the position's **Parts** list, where the
old part's entry has the new part under it. Add the new part as an
entry, then **remove** the old one.

## Check the spares

Open **Maintenance › Spares** on the asset that uses it. The old part's row
shows the demand over the year (failures and planned jobs), the **Hold** that
covers its lead time at its service level, and **Usable now**. If you are
deciding whether to buy and shelve the old part or move to the new one, the
numbers to compare are the failures expected on the old part over the years you
need, and the stock to hold of the new part at its lead time. Price them with
your own supplier prices.
