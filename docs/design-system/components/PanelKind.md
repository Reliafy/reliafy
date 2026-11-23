# PanelKind

The compact title line at the top of a details panel in the Explorer: the row's kind icon and its kind in words, with where it is after a "·" when that helps. "Task · TR-48 mower" after a spanner, "Failure mode" after a bolt, "Function". The file is `frontend/src/components/PanelKind.jsx`; `LevelIcon` (same file) is the icon alone, used in the tree's rows and lists.

## Props

- `type` — the row's kind: `fn`, `std`, `fail`, `mode`, `cause`, `task`.
- children — the kind in words ("Task", "New task", "Failure mode").
- `where` — optional: the position or place it's on, after a "·" in `text-secondary` at 400.
- `title` — optional tooltip (default: the whole line when `where` is given).

## Rules

- One component for a task's title line on the RCM tab and the Maintenance tab, so a task reads the same in both (Derryn, 23 Nov 2026). Don't draw a kind line by hand.
- It sits in the panel's head (`rw-panel-head`) with the panel's own buttons (Expand, ⋯, Close) at the right; the row's name is the `h2` under it.
- `label` weight (600 here, as the head's other kind lines), `text-secondary`, 13/20; the icon is `icon-sm` (14px) in `currentColor`.
