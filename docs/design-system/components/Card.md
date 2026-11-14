# Card

A white card: the page's unit of content. Forms and results sit directly on it; don't nest grey panels inside.

`Card` renders `.card` — `bg-surface`, a 1px `border` border, `radius-lg` (12px), `space-6` (24px) padding, `shadow-sm`, `space-6` between cards.

`CardHeader` is the card's heading row:

- `title` (node) — `heading-sm` (16/24, 600).
- `subtitle` (node, optional) — `small` (13/20) in `text-secondary` under it (max 68ch).
- `actions` (node, optional) — buttons, a select or a figure on the right.
- `level` — heading level, 2 by default (3 inside a section).

Consumer provides the children. Don't put a card inside a card; use a `Section` to divide one.
