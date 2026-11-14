# Tabs

The shared tab row (`components/ui/Tabs.jsx`). It comes in two forms:

- **Scrolling** (the default). On a narrow screen the row scrolls sideways: the hidden side fades out with a chevron that scrolls it, and the active tab is kept in view.
- **With overflow** (`overflow`). The row never scrolls: the tabs that don't fit fold, from the right, into a last tab "⋯ N" (N: how many) that opens a list of them. Use it for a panel with more tabs than a phone's width holds, such as the Explorer's detail panel.

Follows the ARIA tab pattern: only the active tab is in the Tab order (roving tabindex); arrow keys, Home and End move to and open the next tab.

## Props

- `tabs` — `[{id, label, title?, wt?}]`, ordered by use. Leave out a tab a thing doesn't have; never grey it out. The order never changes.
- `value`, `onChange(id)`.
- `label` — accessible name of the row.
- `idPrefix` — ids for the tabs (`${idPrefix}-tab-${id}`) and their panel (`${idPrefix}-panel`).
- `wholeTabs` — on a scrolling row, reveal starts on a whole tab.
- `overflow` — fold what doesn't fit into "⋯ N" instead of scrolling.

## Look

Tabs are `text-secondary` 14px at 500; the active tab is `accent-text` at 600 with a 2px `accent` underline over the row's 1px `border` baseline. Keyboard focus shows `focus-ring-inset`.

"⋯ N" looks like any other tab (`text-secondary`, `text` while its list is open) and is never the active one. Its list is the `ContextMenu` look (`RowMenu`), opened under it, one item per folded tab.

## With overflow: how it fits

- The row takes the width it's given and recomputes when that width, or a tab's label, changes (a `ResizeObserver`; fonts loading count too). Each tab is measured at its widest (the active weight), so the fit doesn't shift when another tab is picked.
- Tabs fold from the right. When anything folds, room is kept for "⋯ N".
- **The selected tab never folds.** Pick one from "⋯" and it takes the last slot that shows; the tab it displaces goes into "⋯". Everything else keeps its order.
- The fitting is a pure function, `fitTabs` in `components/ui/tabsFit.js`, with its own tests.

## Inner views

A tab whose panel has a few views of one thing (Maintenance: Tasks · What it needs · Packages) shows them as a `SegmentedControl` (size "sm") under the tab row: views, not more tabs. Labels are short enough to sit on one line at 400px; put detail such as "(preview)" in the hover text. On a phone (560px and below) the options share the width in equal parts.

## Keyboard

- ← → Home End move along the row, "⋯" included. On a tab they also select it; on "⋯" they only move the focus.
- Enter, Space or ↓ on "⋯" opens its list; ↑ ↓ Home End move in it, Enter chooses, Esc closes it with the focus back on "⋯".
- A tab chosen from the list is selected, shows in the row and takes the focus.

## ARIA

- The row is a `tablist`. The tabs that show are its `tab`s, each `aria-controls` the panel; the panel is a `tabpanel` whose `aria-labelledby` names the selected tab, which always shows.
- "⋯ N" is a `tab` too, so the arrow keys reach it along the row: `aria-selected="false"`, `aria-haspopup="menu"`, `aria-expanded`, and an accessible name that says what's in it ("2 more tabs: Models, History").
- The folded tabs aren't `tab`s while folded: the list's `menuitem`s stand in for them, each named as its tab. Choosing one selects that tab, which then shows in the row as a real `tab`.
