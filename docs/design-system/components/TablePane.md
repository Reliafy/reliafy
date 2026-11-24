# TablePane

What fills the Explorer's table area, the tree kept beside it. Two things use that room, by one mechanism in `views/AssetExplorer.jsx` (`expanded` / `wideDetails`: the table's columns give way and the details or the pane take their room):

- **A row's details, across the table** — the panel that opens beside the table on a click (a task, a work package, a measuring point, a model, an RCM or FME(C)A row, a position's RCM or criticality panel), widened. Its head carries **Expand the details** (⤢) beside, and **Back to table** (⤡) across; `is-expanded` on the panel.
- **Work in the table's room** — `components/TablePane.jsx`: Fit a life model…, Add a prediction…, the RBD builder, Optimise…, Package the tasks…, New mission… and a mission (its setup, phases and answers). A heading saying what it does and for which position, × to go back (Esc does the same). On a phone it takes the screen, with ‹ Back.

## Double-click opens it across the table, everywhere (Derryn, 23 Nov 2026)

- **A single click** picks the row and opens its details beside the table.
- **A double-click** (or Enter, or Open in its menu) opens them across the table, the tree kept beside them.
- **Esc, or Back to table**, puts them beside the table again; Esc once more (or ×) closes them.
- **One rule decides which rows**: `opensWide(r)` in `explorerRcm.js`, read by `TreePane`'s row double-click. Never a per-table list. A row kind whose details open beside the table goes in it (`WIDE_KINDS`, or `opensPanel` for the RCM's rows and positions); its tab's `table.onOpen` opens its details with `setExpanded(true)` on a wide screen; its side panel takes `expanded`, `onExpand`, `onCollapse`, shows ⤢ / ⤡, and its Esc collapses before it closes.
- **A cell edited in place keeps its double-click** (an RCM worksheet cell, a name being edited, a measurement input): `TreePane` skips fields, buttons, links, the chevron and `.rw-c` cells, so the row's double-click applies on the rest of the row.
- **A phone has no "across"**: the details are a sheet that takes the screen.

Rows that open nothing beside the table have no double-click: a position on the Maintenance, Monitoring, Models, Missions and Operations tabs (it's picked; its tabs above the table are its details), a heading row. The Summary tab is the plain tree, not a table: its panel is beside the tree, with no table to cover.

## Props (TablePane.jsx)

- `title`, `subject` — "Add a prediction · Controller".
- `busy` — saving: × is disabled.
- `headingRef` — focused when it opens.
- `actions` — more in the heading, before × ("Open full page").
- `closeLabel` — ×'s name, when "Close <title>" doesn't read ("Close the RBD").
- `bare` — no heading row on a wide screen: the work puts × and its actions in its own toolbar (the RBD builder). The heading stays for screen readers and focus; a phone keeps the row, for ‹ Back.
