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

Choose an asset's name on the **Assets** page and the **Explorer** opens on
that asset alone: its tree, search, tabs and pickers show nothing from any
other asset. The **Explorer** always shows one asset. To look at another, go
back to **Assets** and choose it there.

To see two assets together, merge one into the other. Choose **Merge into
another asset…** from the asset's **⋯** on the **Assets** page (or from its top
row's menu in the Explorer). Pick the asset it joins and where in that asset's
tree it goes; the pane says what comes along before you choose **Merge**.
Everything inside it keeps its history, readings, tasks, RCM and fitted items.
To split it off again, choose **Make this its own asset…** from its row's menu.

## Add positions inside positions

A pump set has a pump and a motor inside it. Open its asset from **Assets**
(it opens in the **Explorer**), pick the pump set and choose **New
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

## Import or export your tree

Already have your hierarchy in a spreadsheet? Bring it in from Excel instead of
adding positions one by one.

1. In the **Explorer**, open the tree's **⋯** menu and choose **Export to
   Excel…**, then **Download Excel**. Even an empty tree gives you the file with
   the right columns, and its **Read me** sheet explains each one.
2. Fill in the **Hierarchy** sheet, one row per position. The **Path** says
   where it sits, every level from the top: `Plant 1 > Unit 2 > Feed pump A`.
   Add its **Tag**, **Position class**, **Location** and the **Fitted item**
   (with its serial, part number and **Installed on** date) if you know them.
   A row's parent must be in the file or already in Reliafy.
3. Choose **Import from Excel…** in the same menu (or on an empty Explorer)
   and pick the file. Reliafy checks every row first and shows what will
   happen ("Will create 312 positions, 40 locations, 18 classes and 290
   items") and any problems, by row, with what to fix.
4. Choose **Import**. It all goes in, or nothing does.

Importing the same file again changes nothing: each row finds its position by
its **ID** (in an exported file), else by its **Path**. So you can export, edit
in Excel and import again:

- Change a **Name**, **Tag** or class and the position is updated.
- Change a **Path** to move a position; the preview says how many will move.
- Nothing is ever deleted. Positions missing from the file stay, and a blank
  cell never clears a value; the preview counts what wasn't in the file.
- An item already fitted is never swapped by an import (close a work order to
  replace it), and its fitted date isn't changed.
- Locations and item classes the file names are made if they don't exist.

To export one part of the tree, choose **Export this branch…** from a
position's row menu. A CSV holds the Hierarchy sheet alone; Excel also has the
Locations and Classes sheets.

## Where to go next

- The Explorer's **Modelling** tab: life models on positions.
- The Explorer's **RCM** tab: decide what to do about each way a position can
  fail.
- **Maintenance → Orders**: the work raised on your positions.
