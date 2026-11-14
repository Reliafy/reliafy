# Button

The app's buttons: a bare `<button>` is the primary style; the other variants are classes on it, so plain markup and the component look alike.

## Variants

- **primary** (no class) — the ONE next-step action in a view: `accent` fill, `text-on-fill` text, `fs-14` at 600, `radius-md`, `shadow-sm`; hover `accent-hover`.
- **secondary** — every other action: `bg-surface`, a `border` outline.
- **ghost** — low-emphasis actions in toolbars and rows: no outline.
- **danger** (`secondary danger`) — destructive actions: `danger` text and outline. Never a red fill.
- **link** — an inline text link that runs an action.
- `size="sm"` (`.sm`) — the compact size used in toolbars, rows and cards.

## Props

`variant` ("primary" | "secondary" | "ghost" | "danger" | "link"), `size` ("sm"), `className`, `type` (default "button"), and any `<button>` attribute.

## Rules

- One primary per view; if there are two candidates, one of them is secondary.
- Labels are verbs in sentence case ("Fit a model", "Compare fits"); "…" when it opens a step that asks for more.
- Every button is `control-md` (32px) tall, `control-sm` (28px) with `sm`, and `control-lg` (40px) on a phone — the same heights as inputs and selects, so a button and a field sit flush in a row.
- Icons inside are `icon-md` (16px).

Source: `frontend/src/components/ui/Button.jsx`; styles in `frontend/src/index.css`.
