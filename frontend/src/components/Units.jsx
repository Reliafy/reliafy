import { UNITLESS, isUnitless } from "../lifeData.js";

// Unit selector for the time column: a combobox of common units that also
// accepts a custom value (free text via the datalist).
const COMMON_UNITS = [
  "Hours",
  "Days",
  "Weeks",
  "Months",
  "Years",
  "Cycles",
  "Kilometres",
  "Miles",
  "Operations",
  "Rounds",
];

export default function Units({ value, onChange }) {
  return (
    <label className="units-field">
      <span className="units-label">Unit of the time (optional)</span>
      <input
        className="units-input"
        list="x-units"
        value={value}
        placeholder="e.g. Hours, Cycles, or type your own"
        onChange={(e) => onChange(e.target.value)}
      />
      <datalist id="x-units">
        {COMMON_UNITS.map((u) => (
          <option value={u} key={u} />
        ))}
      </datalist>
    </label>
  );
}

// A unit the fit flow requires: pick or type one, or tick "No unit" on
// purpose (stored as "units", so results still say "257 units").
export function RequiredUnit({ value, onChange, label = "Unit", listId = "x-units", autoFocus = false }) {
  const none = isUnitless(value);
  return (
    <div className="ds-field ds-unit">
      <label className="ds-unit-pick">
        <span className="ds-label">{label}</span>
        <input
          className="units-input"
          type="text"
          list={listId}
          value={none ? "" : value || ""}
          disabled={none}
          aria-required="true"
          autoFocus={autoFocus}
          placeholder={none ? "No unit" : "e.g. Hours"}
          onChange={(e) => onChange(e.target.value)}
        />
      </label>
      <datalist id={listId}>
        {COMMON_UNITS.map((u) => (
          <option value={u} key={u} />
        ))}
      </datalist>
      <label className="ds-unitless">
        <input type="checkbox" checked={none} onChange={(e) => onChange(e.target.checked ? UNITLESS : "")} />
        No unit (just numbers)
      </label>
    </div>
  );
}
