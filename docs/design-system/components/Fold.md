# Fold

A fold-out part of a form or panel: one quiet line, "› Title", that opens what's under it. Folded with something set inside, the line says what in a few words (its `summary`), so nothing is hidden silently: "› Cost  $40 each time", "› More scheduling options  Also every 6 months, whichever first". Folded with nothing set, it's the title alone. The file is `frontend/src/components/ui/Fold.jsx`.

## Props

- `title` — the words on the line ("Cost", "Labour", "More scheduling options").
- `summary` — what's set inside, one short line, shown only while folded; `""` when nothing is.
- `open` and `onToggle(open)` — controlled (a link that opens one, such as a tree row's `?msec=`); else `defaultOpen`.
- `id` — on the fold, for a link or a scroll to it. `className`, children.

## Rules

- Use it for optional extras and advanced settings that most people leave alone: a task's Cost, Labour and Parts, its More scheduling options. Not for required fields, and not for long guidance (that's a `help` line or a `HelpLink`).
- The summary is the answer, not a description: "1.5 h mechanic", not "Labour is set".
- The line is `label` type (13/20 at 500) in `text-secondary`; the summary is `text` at 400 beside it, wrapping under the title on a narrow panel. The "›" turns when open. The body is indented `space-4` and its fields sit `space-3` apart.
- It's a button with `aria-expanded`: Enter and Space open it, and the focus ring is the global one. Open, its body is a region named by the title.
- Several folds in a row sit `space-1` apart, under one `Section` or ruled block; don't put a fold inside a fold.
