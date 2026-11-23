# TreeTable

The Explorer's tree with a tab's columns beside it: one scroll, one set of rows, the tree as the first column. In code it is `TreePane` (`components/TreePane.jsx`) given `table`; the page (`AssetExplorer`) holds the state. The RCM, FME(C)A, Maintenance tasks, Measurements, Modelling and Missions tabs use it. On the other tabs (Summary, Failure reports, the Maintenance and Monitoring views drawn in the panel) the same `TreePane` draws the plain tree, with the same row menu.

The tree pane and a tab's table are the same tree, not two: what's open, the row picked, a pin and a focus carry from tab to tab in the same arrangement.

## Rows

- Each position (or place) has the tab's own rows under it: its functions and failure modes, its tasks, its measuring points, its models, its missions. Each level rolls up what's at and below it.
- A click picks a row and opens its details beside the table; a double-click (or Enter) opens them across the table, with "Back to table" and Esc to return (`expanded`, `onExpand`, `onCollapse`).
- A row of numbers about another row (the Maintenance tab's Forecast row under a task or package) is one line: a summary run across the columns (`rollupOf`), never a list of dates or periods under it. It opens like any row: a click shows its details beside the table, a double-click or Enter across it (`ForecastSide`, with the shared `ForecastDetails`).
- Columns filter from their headers (`ColumnFilter`); a table that acts on several rows lets you pick them with no row checkboxes: click, Shift-click a range, Ctrl/⌘-click to toggle, Space and Shift+arrows, **Select** on a phone (`table.multi`, see `ColumnFilter`).

## Focus and Pin

Two different things, in every row's menu (`ContextMenu`) on every tab, with the same words. Both sit in the menu's general section: **Focus ›** (one entry; its submenu holds the items below and Clear focus) then **Pin this branch**.

- **Focus here** — this row opened at every level below it, so everything in it shows (every task, failure mode, measuring point or model in that branch), and every other branch closed. The closed branches stay on show: nothing is hidden.
- **The words** name what the open tab shows: Focus tasks (Maintenance), Focus failure modes (RCM, FME(C)A), Focus measurements, Focus models, Focus missions; Focus here on the plain tree or a tab with no table of its own. Focus to a depth › is the same on every tab.
- **Focus to a depth ›** — a submenu, the same on every tab: opened only 1, 2 or 3 levels ("1 level", "2 levels", …; on the RCM tab 4 and 5 too where the rows go that deep). A row with nothing inside it has only Focus here.
- **Pin this branch** — the tree starts at this row: everything above and beside it leaves the tree, the address says so (`?pin=`), and Back undoes it. "Show whole tree" undoes it too.

Focus never pins, and never changes the address. After a focus, rows open and close by hand as usual.

Which rows offer Focus: positions, places, items and classes with something inside them, the RCM and FME(C)A rows, and a tab's own rows that have rows inside them (a model with its Strategy row, a mission with its phases). A tab's leaves (a task, a measuring point) don't: their level's Focus here shows them.

### The way back

While a focus is on (`focused`: `{name, onClear}`):

- The tree column's header says **Focused: <name>** in the accent pill (the look of the filter's pill) with a **Clear focus** button. On a phone (no column headers) the pill sits on its own line under the search box.
- The tree's ⋯ menu has **Clear focus** at the top (beside Show whole tree), and every row's menu has Clear focus after its Focus items.
- Clear focus opens the tree as it was before the first focus (focusing again moves the focus; Clear still goes back to the start). The row picked stays picked.
- A level chosen for the whole tree (the ⋯ menu's levels, Close everything, Reset) ends the focus. A focused row that leaves the tree (deleted, outside a pinned branch) ends it too.

### With the other tools

- **Column filters:** a focus decides what's open; the filters apply inside it. A filter on keeps the way down to its matches as usual, and the filter's values come from the rows open, so focusing a branch narrows the values offered to it.
- **Multi-select:** focusing closes branches, so picks in them leave (picks off screen are dropped, as for any close).
- **Details:** a focus doesn't close the details beside or across the table; the focused row is picked and brought into view.
- **Forecast… and the tab's own actions** stay in the same menu, in its middle section, after Focus › and Pin (the general section) and before the one destructive item.

## Look

- Rows are 30px tall on a wide screen (54px with two lines on a phone), indent 16px a level, the tree column sticky at the left with a `border` right edge.
- The header row is `bg-subtle`, `caption` type in `text-secondary`. Pills in it (Pinned, Focused, Filtered by) are `accent-subtle` with an `accent-border`, `radius-full`, `fs-12` at 500 in `accent-text`; they cut short with the whole text in the tooltip.
