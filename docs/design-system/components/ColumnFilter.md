# ColumnFilter

A tree-table column's filter: a small funnel in the column's header that opens a list of the values in that column, each with how many rows have it. Ticking values keeps only the rows with one of them. In code it is `ColumnFilter` (`components/ColumnFilter.jsx`), drawn by the shared tree-table (`TreePane`) for any table that passes `table.filter`. The Explorer's Maintenance tab (its tasks) is the first to use it.

## How it behaves

- **The values come from what's open in the tree.** Only the rows on show (their branches open) give values, so the list stays short and about the part of the tree you're looking at. Each value's count is how many of those rows have it with the *other* columns' filters applied, so ticking a value never hides its neighbours. A value ticked stays listed (greyed at 0) so it can be unticked.
- **Values in one column are "any of"; columns together are "all of".**
- **A filter hides the rows that don't match and keeps the way down to the ones that do.** A parent row with nothing matching at or below it leaves the tree; the top rows stay. Roll-ups ("3 tasks at and below") count only what matches. What's open stays open.
- **It shows that it's on.** The funnel is filled (`accent-subtle` with an `accent-border`, the icon in `accent-text`) and its name says how many values are ticked ("Filter Trade (1 chosen)"). The tree column's header reads "Filtered by Trade, Packaged" in an accent pill with a **Clear** button that turns every filter off in one click. Each list has its own **Clear** for that column.
- **A column with more than one facet** lists each under a heading: Interval has its unit, then the interval itself.

## On a phone

There are no column headers, so one **Filter** button (with the count when on) under the search box holds every column's values, a section each. The same "Filtered by …" pill and **Clear** sit beside it. Items are 40px tall.

## Props

- `label` — the column's name ("Kind"); "Filter" for the phone's button.
- `facets` — `[{id, label, values: [{value, label, count}]}]`.
- `chosen` — `{facet id: [values ticked]}`.
- `onChange(facetId, values)`, `onClear()`.
- `wide` — the phone's button: its label shown, not only the funnel.

The table passes `table.filter = {chosen, facetsFor(colId), facetsAll(), onChange, onClearCol(colId), onClear, words}`; `words` is the "Filtered by …" text, empty when no filter is on.

## Look

- The button is 20 × 20 px, `radius-sm`, `text-tertiary` until hovered (`accent-wash`) or on.
- The list is a `bg-surface` card with a 1px `border`, `radius-lg`, `shadow-lg`, 240px wide (the screen less 32px on a phone), at most 60% of the window tall, scrolling inside. It is drawn in the shared portal host, placed under its button and moved in to stay 8px from every edge.
- Items: a checkbox, the value in `fs-13`, the count in `fs-12` `text-secondary` with tabular numerals. A value with no rows left is `text-tertiary`.
- The foot: "From the rows open in the tree" in `help` type, then **Clear**.

## Keyboard

The button is in the header (Tab reaches it). Opening the list puts the focus on its first box; Space ticks, Tab moves on. Esc closes it and returns the focus to the button; a click away or a scroll of the table closes it too. While it's open the page's own Esc (closing a pane) waits (`hasOpenLayer` knows `.cf-pop`).

## Selecting rows in the same table

A table that acts on several rows at once passes `table.multi = {picked, can(row), onClick(key, event), onToggle(key), onMenu(key)}`:

- A click picks the row alone (and opens its details as before); Shift-click picks every pickable row between it and the last one clicked, as drawn; Ctrl/⌘-click adds or takes one without opening anything.
- **No checkboxes on rows** (Derryn, 22 Nov 2026): a row's picked look is the selection. Keyboard: arrows move, Space adds or takes the focused row, Shift+↑/↓ extends the pick. Phone: the row's ⋯ menu has **Select**, which starts picking by tap until **Done** or **Clear**.
- While rows are picked the tree column's header (under the search box on a phone) shows **N selected** in the accent pill with **Clear** (and **Done** while picking by tap).
- Picked rows use the shared `.picked` look (`accent-subtle` with the accent bar) and `aria-selected`; the grid is `aria-multiselectable`.
- Right-click (or the row's ⋯, or a long press on a phone) on a picked row acts on all the picked rows; on any other row it picks that row alone first. The menu's labels name the action, and the pane it opens says how many rows it's for.
- Picks that leave the screen (a branch closed, a filter, a read) are dropped.
