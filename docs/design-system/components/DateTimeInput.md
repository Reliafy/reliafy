# DateTimeInput

The one date field and the one time field (`components/ui/DateTimeInput.jsx`): `DateInput`, `TimeInput`, and `DateTimeInput` for a day and a time together. Never the browser's own `<input type="date">` or `type="time"`: those follow the browser's language, so an English (US) browser shows "11/22/2026" and "04:00 PM". These show **"22 Nov 2026"** and **"16:00"** whatever the browser is set to, as every date on a page does (`dates.js`).

## Behaviour

- The value in and out is ISO, as the browser's: `"2026-11-22"`, `"16:00"`, `"2026-11-22T16:00"`. `onChange` gets an event-like `{target: {value}}`, so one stands in for the other.
- Typing is day first: "22/11/2026", "22-11-2026", "22 Nov 2026" or ISO; on leaving the field "22/11/26" and "22 Nov" (this year) are taken too, and the text then reads "22 Nov 2026". Month-first text isn't taken.
- Times: "8", "830", "8:30", "20:00", "8pm" all read as a 24-hour time on leaving ("08:00", "08:30", "20:00").
- Half-typed text hands nothing back until the field is left; text left that isn't a day or a time hands back `""` and the box is marked invalid.
- The date field's calendar button opens the browser's own picker; what it picks comes back as an ISO day. `picker={false}` drops the button (a table cell's editor, which closes when it loses focus).
- `TextInput type="date"` and `type="time"` render these, so a `Field` with a `TextInput` needs no change.

## Props

- `value`, `onChange(e)`, `min`, `max` (ISO days; a day outside them is marked invalid), `disabled`, `readOnly`, `required`, `autoFocus`, `id`, `aria-label`, `className` (on the text box), `onBlur`, `onKeyDown`.

Sizes: the date box is about 9.5em plus its button, the time box 5em; neither stretches to its container. Inside a `Field` they take its id, help and error wiring.

`dateFields.test.js` fails on a browser date or time field anywhere in the app.
