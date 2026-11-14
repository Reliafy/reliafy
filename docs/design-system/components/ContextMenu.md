# ContextMenu

The right-click menu: a thing's own actions at the pointer — a row in the Explorer tree, a block or link on the RBD canvas. In code it is `RowMenu` (`components/RowMenu.jsx`); the RBD canvas draws the same look itself (`.rbd-menu`).

## How it opens

Right-click, the row's ⋯ button (`MoreMenu`), or Shift+F10 / the Menu key on a focused row. Every action in it must also be reachable another way (a ⋯ button or a toolbar); the right-click is a shortcut, never the only door.

## Props

- `items` — `[{id, label, danger?, disabled?, reason?, items?, checked?} | {separator: true}]`.
  - `danger` — a destructive action in `danger-text`, last in the menu.
  - `disabled` + `reason` — the item stays in the menu, greyed, with the reason in `help` type under it (and as its description to a screen reader). Don't hide what can't be used now; say why.
  - `items` — a submenu ("Focus ›"). It opens beside the menu on a wide screen, in place under its item on a phone.
  - `checked` (true | false) — a radio in a submenu, ticked with ✓.
  - `separator` — a `border` line between groups; the arrow keys pass over it.
- `at` — `{x, y}`, the pointer or the corner of what opened it. The menu moves in to stay on screen.
- `label` — the menu's name ("Actions for Feed pump").
- `anchorId` — the row it belongs to: a scroll that moves the row away closes the menu.
- `onChoose(id)` — runs after the menu has closed.
- `onClose()` — puts the focus back on the row.

## Look

- A `bg-surface` card with a 1px `border`, `radius-lg`, `shadow-lg` and 4px padding. 200px at least.
- Items are `fs-13` at 500 in `text`, `radius-md`, 7px × 10px padding.
- Hover and keyboard focus show `accent-subtle` with `accent-text`. Danger items hover in `danger-bg`.
- An open submenu's item stays tinted. The submenu sits 4px beside it.

## Keyboard

The first item takes focus. ↑ ↓ Home End move, Enter or Space chooses, → opens a submenu and ← or Esc goes back to its item. Esc or Tab closes the menu.

## Order

Go first (Open in the tree), then edit, then structure (count, focus, move), then remove. Use one danger item at most, at the end, after a separator. Labels are verbs in sentence case; "…" when the item opens a dialog.
