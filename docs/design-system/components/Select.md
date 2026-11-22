# Select

One value from a list, as a styled drop-down: a trigger button (`role="combobox"`) that opens a listbox under it (above it near the bottom of the screen), drawn in a portal so a card or dialog never clips it. It replaces the native `<select>`, whose list can't be themed. The chosen row carries a ✓, so it isn't shown by colour alone. The file is `frontend/src/components/Select.jsx`.

## Props

- `options`: `[{value, label, hint?, disabled?}]`, or plain strings. `{heading}` is a group title that can't be chosen. `hint` is a quiet second line under the label.
- `value`, `onChange(value)`: `onChange` runs only when the value changes.
- `placeholder`: what the trigger says with nothing chosen.
- `searchable`: a "Find…" box at the top of the open list. Typing narrows it to the rows whose label or hint hold every word typed, in any order and case (`selectSearch.js`). Enter picks the first match.
  - Typing a letter on the closed trigger opens it with that letter already in the box (type-ahead).
- `ariaLabel`, `title`, `disabled`, `className` (`sel-embedded`: borderless, inside a bordered parent).

## Keyboard

↑ ↓ move, Home and End jump, Enter or Tab chooses, and Escape closes and returns focus to the trigger. Enter, Space or an arrow on the closed trigger opens it.

## When to use it

- 2–5 short options where seeing them all helps: `ChoiceChips` instead.
- More than about 15 options: make it `searchable`.
- A long list of things in a tree, such as positions: `PositionPicker` (`MaintenanceParts.jsx`). It's this Select, searchable, with each position's tag in its label ("P-101 · Filter pump") and the way down to it as the hint ("Pump station › Skid 2"), from `positionPicker.js`. Use it for every "which position" field (a new work order, Move to a position, a parts list), never a native `<select>`. On a big site the list has hundreds of rows, so people find a position by typing its tag, name or system.
- Searching the server as you type (a library of thousands): a combobox with its own results list, such as `LibraryRecordPicker`, not this.

## Look

The trigger is a control (`control-md`, `control-lg` on a phone) with `border-control`. The open list is `bg-surface` with `radius-lg` and `shadow-lg`, at most 280px tall, and never wider than the screen less 32px. A hint is `fs-12` in `text-secondary`.
