# TaskExtras

A task's optional extras, **Cost**, **Labour**, **Parts** and **Tools and method** (tools, consumables, access, method and instructions), each a `Fold` with one line saying what's set ("$40 each time", "1.5 h mechanic", "Spindle kit × 1"). One component for both tabs (Derryn, 23 Nov 2026): the Maintenance tab's task panel edits them (with a corrective response's "Cost of the failure itself" as a fourth); the RCM tab's task panel reads them under **Cost and needs**, each with the way to change it on the Maintenance tab (`?msec=`). The file is `frontend/src/components/TaskExtras.jsx`; the words come from `taskExtras.js`, the same as the tree's rows under a task.

## Props

- `items` — `[{key, title, summary, body, id?, ref?}]` in order; a `null` is skipped.
- `open` (`{key: true}`) and `onToggle(key, open)` — which are open (a tree row's `?msec=` opens one).
- `className`.

## Rules

- The summary says what's set, in the words of `taskExtras.js`; nothing set, the title alone. A cost from the LSA (nothing typed) says so: "$45 each time, from its LSA".
- Folds sit `space-1` apart; don't add help paragraphs between them.
- Read-only (RCM), a body is one quiet line with one action ("Change in Maintenance ›"), never a form.
