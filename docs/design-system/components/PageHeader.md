# PageHeader

A page's header: breadcrumb, the item's own name, one muted meta line, and actions on the right — one primary (the next step), the rest secondary, and a ⋯ menu that also holds "Copy ID".

## Props

- `crumbs` — `[{label, to}]`, the parents only; the title names the page.
- `title` — the item's name (`fs-24`, 600).
- `badges` — chips after the title (Sample, Shared, Unsaved).
- `meta` — one muted line (kind, unit, when saved).
- `primary` — the one primary button, if this view has a next step.
- `actions` — secondary buttons, shown before the primary.
- `menu` — `.ovm-item` buttons for the ⋯ menu (share, delete last).
- `id` — adds "Copy ID" to the menu.
- `children` — extra content under the meta line.

Always show the unit in the meta line.
