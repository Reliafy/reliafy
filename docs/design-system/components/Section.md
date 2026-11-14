# Section

A section of a panel or form: a 14px heading (`psec-title`), a count pill, and one small action at the right ("+ Add", "Change…"). Sections sit 16px (`space-4`) apart with a quiet `border-subtle` between them.

## Props

- `title`, `count` (a number or null), `headingLevel` (3 by default).
- `action` — `{label, onClick, ariaLabel?, plus?: true, disabled?, ref?}`: `plus` makes it a ghost "+ Add", else a small secondary.
- `tip` — a few words of guidance behind a small "?" by the heading, shown on press.
- `aside` — a node between heading and action (a sort, "✓ Saved").
- `label`, `id`, `className`, children.

`AddRow` (same file) is the dashed "+ Add …" row that ends a list.
