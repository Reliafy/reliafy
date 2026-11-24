# SegmentedControl

A row of mutually exclusive options: sans, sentence case, the chosen option tinted in the accent (`accent-subtle` fill, `accent-text` text, an `accent-border` outline; buttons `control-md` tall).

## Props

- `options` — `[{value, label, title?, disabled?}]`.
- `value`, `onChange(value)`.
- `label` — accessible name of the group (shown above it with `showLabel`).
- `fill` — opt-in: the control spans the full width and the segments split it equally (`flex: 1 1 0`), never a short row inside a long outline.
- `size` — "sm" for the compact size inside cards and toolbars.

Use to switch a VIEW of the same thing (a chart's plot, a scale), or the way in to one step (where a fit's data comes from: Saved data · Paste or type · Upload a file; a mission's Start: Now · On a date, and Calendar: Linked to Operations · Its own duty, each showing the fields under it). For a value that's saved, use `ChoiceChips`; for navigation between panels, `Tabs`.

## Width rule

One rule everywhere: the control is only as wide as its options (`width: fit-content`, `max-width: 100%`), with the same `space-3` padding on every segment, even inside a column or a form field that would stretch it. It never stretches by default, at any screen width. Where a full-width control is wanted (for example a primary choice on a phone), pass `fill`: the segments then split the width equally. Don't add `align-self` or `width` overrides in a page's CSS; use `fill` or the default.

When its column is narrower than its options (a side panel, a phone), the segments shrink and their words wrap onto a second line. A segment is never clipped by the outline.
