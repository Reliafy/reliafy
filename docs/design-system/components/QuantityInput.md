# QuantityInput

A number and its unit as one control: "10 | flight hours ▾", "8 | h a day", "50 | %". One `border-control` box, one `focus-ring` round the whole thing (never one per half), a number box sized to the numbers it takes, and the unit inside the box, so the value is always read with it. It's an `InputGroup` underneath. The file is `frontend/src/components/ui/QuantityInput.jsx`.

## Props

- `label` — the number's accessible name ("Length", "Hours a day"). Put the visible words on the `Field` round it; the group itself has no name, so a label finds one control.
- `value`, `onChange(text)` — the number as typed, a string; the caller parses and checks it.
- The unit, one of:
  - `suffix` — fixed words in an `Addon` ("h a day", "%", the model's unit);
  - `units` (`[{value, label}]` or strings), `unit`, `onUnitChange(value)` — a choice of units as an embedded `Select`; `unitLabel` names it (default "<label> unit").
- `chars` — the number box's width in digits (default 6; 3–4 for a percentage or days a week, 8 for an age).
- `type` — `"number"` (default: a spinbutton with the browser's spinners hidden) or `"text"` where people type "9,000".
- `min`, `max`, `step` (default `any`), `inputMode` (default `decimal`; `numeric` for whole numbers), `placeholder`, `disabled`, `invalid`, `id`, `title`.

Inside a `Field`, the number takes the field's id, help and error (the box turns red with it); the unit drop-down gets `<field id>-unit`, so ids stay unique.

## Rules

- Use it for every number that has a unit: a mission's length, a phase's duration, a duty's hours a day and days a week, an age, a percentage, a task's How often ("Every [50 | operating hours ▾]") and its second limit, a response's labour hours. Never a bare number box with the unit as loose text beside it, and never a number box and a separate drop-down side by side.
- It's only as wide as it needs (`width: fit-content`, never wider than its column). Don't stretch it to a column's width.
- No spinners: people type numbers. Arrow keys still step a `type="number"` field.
- The help under it says what the number is in, in a few words ("In flight hours. Cycles or km need a rate per hour.").
- A sentence with fields in it ("About [8] hours a [day ▾]", Operations' duty) is a different pattern and stays one.
