# SegmentedControl

A row of mutually exclusive options: sans, sentence case, the chosen option tinted in the accent (`accent-subtle` fill, `accent-text` text, an `accent-border` outline; buttons `control-md` tall).

## Props

- `options` — `[{value, label, title?, disabled?}]`.
- `value`, `onChange(value)`.
- `label` — accessible name of the group (shown above it with `showLabel`).
- `size` — "sm" for the compact size inside cards and toolbars.

Use to switch a VIEW of the same thing (a chart's plot, a scale). For a value that's saved, use `ChoiceChips`; for navigation between panels, `Tabs`.
