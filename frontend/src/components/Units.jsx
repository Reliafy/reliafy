import Field, { useField } from "./ui/Field.jsx";
import { Checkbox, TextInput } from "./ui/Controls.jsx";
import { UNITLESS, UNIT_MISSING, isUnitless, unitSettled } from "../lifeData.js";

// Common units for a model's values, offered by every unit box (a datalist, so
// any other unit can be typed). Not only time: x may be cycles, km, volts or a load.
export const COMMON_UNITS = [
  "Hours",
  "Days",
  "Weeks",
  "Months",
  "Years",
  "Operating hours",
  "Cycles",
  "Starts",
  "Kilometres",
  "Miles",
  "Operations",
  "Rounds",
  "Volts",
  "kV",
  "MPa",
];

function UnitControls({ value, onChange, label, listId, autoFocus }) {
  const field = useField();
  const none = isUnitless(value);
  return (
    <span className="unit-field-row">
      <TextInput
        list={listId}
        aria-label={label}
        aria-describedby={field?.describedBy}
        aria-required={!none}
        value={none ? "" : value || ""}
        disabled={none}
        autoFocus={autoFocus}
        placeholder={none ? "No unit" : "e.g. hours, cycles, km"}
        onChange={(e) => onChange(e.target.value)}
      />
      <datalist id={listId}>
        {COMMON_UNITS.map((u) => (
          <option value={u} key={u} />
        ))}
      </datalist>
      <Checkbox className="ds-unitless" checked={none} onChange={(e) => onChange(e.target.checked ? UNITLESS : "")}
                label="No unit (just numbers)" />
    </span>
  );
}

// The unit of a model's times, where it is typed: one required choice before
// a model is fitted or created (a unit, or "No unit" ticked, stored as
// UNITLESS so results read "257 units"). It starts empty, with no default:
// a model fitted in days read as hours is 24 times out. While it is empty,
// the line under it says what to do (``why``); the caller keeps its own
// action unavailable until unitSettled(value).
export default function Units({
  value, onChange, label = "Unit of the times", listId = "x-units", autoFocus = false, why = UNIT_MISSING, className = "",
}) {
  return (
    <Field as="fieldset" label={label} help={unitSettled(value) ? null : why}
           className={"unit-field" + (className ? ` ${className}` : "")}>
      <UnitControls value={value} onChange={onChange} label={label} listId={listId} autoFocus={autoFocus} />
    </Field>
  );
}
