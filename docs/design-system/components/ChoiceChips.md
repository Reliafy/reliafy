# ChoiceChips

One choice from a few, as chips: the chosen one filled with `accent-subtle`, an inset `accent` ring and a ✓, so it isn't shown by colour alone. A radio group: ← → (and ↑ ↓) move and choose, Tab leaves.

## Props

- `options` — `[{value, label, title?}]` (title: the chip's tooltip).
- `value` — the chosen value ("" or null: none).
- `onChange(value | "")`.
- `clearable` — choosing the chosen one again clears it.
- `moveOnly` — arrows move focus only; Enter, Space or a click chooses (a popover where each choice saves at once).
- `label`, `disabled`, `autoFocus`.

Use for 2–5 short options where seeing them all helps; more than that, a `Select`. Chips are `control-sm` tall (`control-lg` on a phone).
