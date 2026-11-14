# Field

A form field: the label, an "optional" marker beside it, a slot at the label's right end (a character counter, or "✓ Saved" for 2 s after a save), the control, then ONE line under it: an error (red, with a round "!" and `role="alert"`) or else the help. Never both.

## Props

- `label` — the words over the control (its accessible name); `labelHidden` keeps it for screen readers only.
- `optional` — "optional" beside the label, quieter (`text-tertiary`), not in brackets.
- `help` — one line of help (`help`: 12/16 in `text-secondary`).
- `error` — the reason a value isn't kept; the control is marked invalid.
- `count` — a node at the label's end (e.g. `<CharCount>`).
- `saved` — a number that changes on each save: "✓ Saved" shows for 2 s.
- `as` — "div" (default) or "fieldset" for a group (comparator + value + unit).

The control is the child: `TextInput`, `TextArea` (starts at one line and grows) and `Select` render `.ctl` — `bg-surface`, a 1px `border-control` (3:1, so the box is visible), `control-md` tall, `fs-14` (16px on a phone so iOS doesn't zoom), the `focus-ring` ring, `danger` border, `danger-bg` fill and `danger-text` message on an error.

Errors say what to do ("Enter a time above 0."), not what went wrong in code.
