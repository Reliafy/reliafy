# Tabs

The shared tab row. On a narrow screen the row scrolls sideways: the hidden side fades out with a chevron that scrolls it, and the active tab is kept in view.

Follows the ARIA tab pattern: only the active tab is in the Tab order (roving tabindex); arrow keys, Home and End move to and open the next tab.

## Props

- `tabs` — `[{id, label, title?, wt?}]`.
- `value`, `onChange(id)`.
- `label` — accessible name of the row.
- `idPrefix` — ids for the tabs and their panel (`${idPrefix}-panel`).
- `wholeTabs` — on a scrolling row, reveal starts on a whole tab.

Tabs are `text-secondary` 14px at 500; the active tab is `accent-text` at 600 with a 2px `accent` underline over the row's 1px `border` baseline.
