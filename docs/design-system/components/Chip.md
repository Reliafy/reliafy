# Chip

A small label: 12px sans, sentence case, 6px radius (`radius-md`). Colour only when it means something.

## Tones

- **neutral** (default) — a kind, a source, a flag ("Sample", "Shared").
- **accent** — the current or chosen thing ("Current plan", "Suggested").
- **success** — a good verdict ("Supported", "Healthy"): `success-text` on `success-bg`.
- **warning** — a caveat ("Simulated", "Unsaved", "Plan replacement"): `warning-text` on `warning-bg`.
- **danger** — a bad verdict ("Contradicted", "Replace now"): `danger-text` on `danger-bg`.

## Props

`tone`, `dot` (a CSS colour: a small dot before the text, e.g. a distribution's chart colour), `onClick` (renders a `<button>` — an editable value such as a decision), `className`, children (the words).

The words carry the meaning; colour only reinforces it.
