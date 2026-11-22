# Field

A form field: the label, an "optional" marker beside it, a slot at the label's right end (a character counter, or "✓ Saved" for 2 s after a save), the control, then ONE line under it: an error (red, with a round "!" and `role="alert"`) or else the help. Never both.

## Props

- `label` — the words over the control (its accessible name); `labelHidden` keeps it for screen readers only.
- `optional` — "optional" beside the label, quieter (`text-tertiary`), not in brackets.
- `help` — one line of help (`help`: 12/16 in `text-secondary`).
- `error` — the reason a value isn't kept; the control is marked invalid.
- `count` — a node at the label's end (e.g. `<CharCount>`).
- `saved` — a number that changes on each save: "✓ Saved" shows for 2 s.
- `as` — "div" (default) or "fieldset" for a group (comparator + value + unit, a list of checkboxes); the group is named by its label.

The control is the child: `TextInput`, `TextArea` (starts at one line and grows) and `Select` render `.ctl` — `bg-surface`, a 1px `border-control` (3:1, so the box is visible), `control-md` tall, `fs-14` (16px on a phone so iOS doesn't zoom), the `focus-ring` ring, `danger` border, `danger-bg` fill and `danger-text` message on an error.

A date or a time is `TextInput type="date"` / `type="time"`, which render the shared `DateTimeInput` fields ("22 Nov 2026", "16:00"), never the browser's own.

`Checkbox` (same file as `TextInput`) is a checkbox with its label beside it (`.check`): the whole label is the target, a 16px (`icon-md`) box in `accent`, the label in `body` text, and the row 40px tall on a phone. Use it for a yes/no in a form that waits for Save ("Counted in running hours"); a setting that applies at once is a `Switch`. Several of them (which failure modes a task prevents) go in one `<Field as="fieldset">`, whose label names the group.

Without a `label`, `Checkbox` is the box alone (`.check-bare`): a row-select box in a table, or a box under a column heading that names it. Pass `aria-label` (it names the row: "Use pump 3"). It adds no row padding, and on a phone an invisible 40px (`control-lg`) target surrounds it, so the row keeps its height.

`Radio` (same file) is one choice of several, on the same `.check` row: a native radio, so its `name` groups it and ← → move within the group. Use it where an option carries long text, a hint under it, or a control of its own ("Only these levels: …"). Short options are `ChoiceChips` (a saved value) or a `SegmentedControl` (a view). A group of them goes in one `<Field as="fieldset">` (or a `role="radiogroup"` with an `aria-label`).

A long `Select` takes `searchable`: a "Find…" box at the top of the list. Every word typed must appear in an option's name or hint; within each group the closest names come first (exact, then starts with, then holds the phrase), the closest match is highlighted, and Enter takes it (`selectSearch.js`).

Errors say what to do ("Enter a time above 0."), not what went wrong in code.
