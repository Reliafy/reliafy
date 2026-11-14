# GroupedTabs

A short tab row where some tabs are drop-downs: `Summary | Analysis ▾ | Operation ▾ | History ▾`. Use it when a panel has more views than a tab row can hold at phone width and they fall into a few plain groups. In code it is `components/ui/GroupedTabs.jsx`. The Explorer's detail panel uses it (behind `EXPLORER_GROUPED_TABS` in `explorerTabs.js`).

## How it behaves

- A **plain group** (one entry named as the group, such as Summary) is an ordinary tab.
- The other groups open a `ContextMenu` (`RowMenu`) of their entries under the tab. The entry shown is ticked (`checked`).
- The tab of the group the panel is in is the active tab, and it names the entry shown: "Operation: Maintenance ▾". On a narrow screen (560px and below) it shows the entry alone ("Maintenance ▾"), and the full name stays its accessible name. An entry with inner views but only one for this row names that view too ("Monitoring › Risk now").
- When the entry shown has **inner views** (Maintenance: Tasks · What it needs · Packages), they follow the tabs as a `SegmentedControl` (size "sm"): views of one thing, not more tabs. At 560px and below they share the width in equal parts and a long label wraps.
- The row wraps rather than scrolling sideways. Nothing scrolls the page sideways at 400px.
- Leave out entries a row doesn't have, and a group with no entries. Never grey them out.

## Props

- `groups` — `[{id, label, title?, entries: [{id, label, title?, views: [{id, label, title?}]}]}]`.
- `at` — `{group, entry, view}`: where the panel is.
- `onChoose(entryId, viewId | null)` — an entry picked from a menu (`null`: its first view), or an inner view picked.
- `label` — the row's accessible name.
- `idPrefix` — ids for the tabs (`${idPrefix}-tab-${group}`) and the panel they control (`${idPrefix}-panel`), as `Tabs`.
- `labelOf(group, at, {short})` — the words on a group's tab; `isPlain(group)` — is it a plain tab.

## Look

The same as `Tabs`: `text-secondary` 14px at 500; the active tab `accent-text` at 600 with a 2px `accent` underline over the row's 1px `border` baseline. The ▾ is `fs-12` in `text-tertiary` (`accent-text` on the active tab). A tab whose menu is open is `text`. Tabs are `control-md` tall (`control-lg` at 560px and below, for touch), with `space-3` sides (`space-2` narrow). Keyboard focus shows `focus-ring-inset`. The menu is the `ContextMenu` look.

## Keyboard

The row is one stop in the Tab order (a roving tabindex on the active tab). ← → Home End move along the row without opening anything. ↓, Enter or Space opens a group's menu; in it ↑ ↓ move, Enter chooses, and Esc closes it with the focus back on its tab. A plain tab opens on Enter or Space.

## ARIA

The row is a `tablist`; each group is a `tab` (`aria-selected` on the group the panel is in), and a group with a menu also has `aria-haspopup="menu"` and `aria-expanded`. The panel's `aria-labelledby` names the group's tab.
