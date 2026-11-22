# Select

One value from a list, as a styled drop-down: a trigger button (`role="combobox"`) that opens a listbox under it (above it near the bottom of the screen), drawn in a portal so a card or dialog never clips it. It replaces the native `<select>`, whose list can't be themed. The chosen row carries a ✓, so it isn't shown by colour alone. The file is `frontend/src/components/Select.jsx`.

## Props

- `options`: `[{value, label, hint?, disabled?}]`, or plain strings. `{heading}` is a group title that can't be chosen. `hint` is a quiet second line under the label.
- Or the rows as `<option>` and `<optgroup>` children, written as for a native `<select>` (`selectOptions.js`). Then every value is a string, and when `value` matches no row the first row that isn't disabled shows, as a browser does.
- `value`, `onChange(value)`: `onChange` runs only when the value changes.
- `placeholder`: what the trigger says with nothing chosen.
- `searchable`: on by itself for more than 15 rows; `searchable={false}` turns it off, `true` turns it on for a short list. A "Find…" box at the top of the open list. Typing narrows it to the rows whose label or hint hold every word typed, in any order and case (`selectSearch.js`). Enter picks the first match.
  - Typing a letter on the closed trigger opens it with that letter already in the box (type-ahead).
- `ariaLabel` (or `aria-label`), `title`, `disabled`, `id`, `autoFocus`, `onBlur`, `className` (`sel-embedded`: borderless, inside a bordered parent).
- `ref` reaches the trigger button (to focus it). `onKeyDown` gets the keys pressed while the list is shut, before Select's own (an in-cell editor's Escape); `preventDefault()` keeps Select from acting on one.
- Inside a `<Field>` the trigger takes the field's id, help and error (`aria-invalid` draws it red), so the field's label names it.
- The trigger carries the chosen value as `data-value`, and each row its value, so a smoke test can read and pick them (`smoke/select.js`: `choose`, `expectChosen`, `optionLabels`).

## In a form: `ui/Controls`' Select

`Select` from `components/ui/Controls.jsx` is this same component, written like a form control: `<option>` children, and `onChange` gets `{ target: { value, name } }`, so a form's handlers read the same as for `TextInput`. Its text is `fs-14` like the inputs beside it, and it joins an `InputGroup`. Use it in forms; use this one directly where `onChange(value)` and an `options` array read better. Never a native `<select>`: lint fails on one outside these two files.

## Keyboard

↑ ↓ move, Home and End jump, Enter or Tab chooses, and Escape closes and returns focus to the trigger. Enter, Space or an arrow on the closed trigger opens it. Escape shuts only the list, never the form or dialog round it. Clicking a row leaves focus on the trigger. Focus stays on the trigger (or the search box) and `aria-activedescendant` names the row a screen reader should read.

## Behaviour

- The open list follows its trigger when a pane or dialog scrolls, and shuts once the trigger is out of sight or on a click outside.
- A row shown only because the value matches none (a native list shows its first row) isn't ticked, and choosing it still calls `onChange`.

## When to use it

- 2–5 short options where seeing them all helps: `ChoiceChips` instead.
- More than about 15 options: make it `searchable`.
- A long list of things in a tree, such as positions: `PositionPicker` (`MaintenanceParts.jsx`). It's this Select, searchable, with each position's tag in its label ("P-101 · Filter pump") and the way down to it as the hint ("Pump station › Skid 2"), from `positionPicker.js`. Use it for every "which position" field (a new work order, Move to a position, a parts list), never a native `<select>`. On a big site the list has hundreds of rows, so people find a position by typing its tag, name or system.
- Searching the server as you type (a library of thousands): a combobox with its own results list, such as `LibraryRecordPicker`, not this.

## Look

The trigger is a control (`control-md`, `control-lg` on a phone) with `border-control`, `border-control-hover` on hover and the focus ring when open or focused; `fs-13` text at weight 400, like a text box (`fs-14` in a form). On a phone each row is `control-lg` tall and the search box takes 16px text, so iOS doesn't zoom. The open list is `bg-surface` with `radius-lg` and `shadow-lg`, at most 280px tall, and never wider than the screen less 32px. A hint is `fs-12` in `text-secondary`.
