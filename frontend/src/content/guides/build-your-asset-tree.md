---
title: "Build your asset tree: places, positions and items"
task: "How do I add a site, put positions (pumps, motors, valves) at it and fit the items that fill them?"
category: "Maintenance strategy"
prerequisites: "Reliafy Maintenance."
order: 25
# Reliafy Maintenance is operators-only for now: this guide is linked from the
# Assets page itself and stays out of the index until Maintenance opens.
hidden: true
---

Your asset tree has three kinds of thing in it:

- **Places** (an asset and the areas inside it): a site, a pumping station, a
  pump hall. Where things physically are.
- **Positions**: the jobs that need doing at a place, each a slot something
  fills. "Duty pump", "Standby pump", the motor inside each. A position keeps
  its history whatever is fitted to it.
- **Items**: the serial-numbered things fitted to positions (or kept as
  spares at a place). An item can move; its history follows it.

## Start with an asset

1. Open **Assets** and choose **New asset**. Give it the name
   of the site (for example "Riverside pumping station").
2. The asset's page opens. Its main button is **Add a position here**: add the
   first position (for example "Pump set 1"). Its **Location** is filled with
   the asset, so it shows at the site straight away.
3. Add the areas inside the asset (a pump hall, a valve pit) with
   **Location inside**, if you want them. A position can be at any of them.

## Add positions inside positions

A pump set has a pump and a motor inside it. Open the
**Explorer** (under Assets), pick the pump set and choose **New
position inside** from its row's menu (right-click, or its **⋯**). A position
inside another is wherever that one is, unless you give it a place of its own.

In the Explorer arranged by **Locations**, a place's menu has **New position
here** too: the new position is at that place.

## Fit the items

Open a position's own page (**Open the full page** in the details' **…**
menu); **Fit an item** there records what's fitted and when. **Open
in the Explorer** takes you back to the tree.
Replacing it later is done by closing a work order, so the old item's life (and
whether it failed) goes into the position's history.

## Where to go next

- The Explorer's **Modelling** tab: life models on positions.
- The Explorer's **RCM** tab: decide what to do about each way a position can
  fail.
- **Maintenance → Orders**: the work raised on your positions.
