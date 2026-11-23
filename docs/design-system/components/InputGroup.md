# InputGroup

Controls joined into one: a comparator, a value and its unit, or an interval and its unit. The unit sits inside the box (an `Addon`, or a select at the end), so it's always read with its value. The group draws one border and one `focus-ring` ring around them.

## Parts

- `InputGroup` — `label` (the group's accessible name), children: `.ctl` controls and `Addon`s.
- `Addon` — fixed words inside the group ("ppm", "weeks"), on `bg-subtle`.
- `ReadsAs` — what the value will read as, under the controls ("Reads as: … between 80 and 120 ppm"); nothing when there's nothing to read yet.

Always show the unit. Times and parameters are in the model's time unit.

A plain number and its unit is the shared `QuantityInput` (built on this): use it rather than writing the group by hand. Use `InputGroup` itself for other joins (a comparator and a value, a count and a name).

## Focus

The group draws the one ring (`:focus-within`); the controls inside never draw their own, even in a panel whose own input rule would (`.rw-panel`). The joined controls keep no border of their own: a hairline `border` divides them.
