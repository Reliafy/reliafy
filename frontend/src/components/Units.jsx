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

// The fit flow's unit: optional. Pick or type one so results say what the
// numbers mean; tick "No unit" to say there is none (stored as "units", so
// results still say "257 units"). Left blank it just fits without one.
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
      {!none && !String(value ?? "").trim() && (
        <span className="ds-hint">
          Add a unit (Hours, Days, Cycles…) so results say what the numbers mean. Without one,
          results have no unit: times are in whatever unit your data uses.
        </span>
      )}
      <label className="ds-unitless">
        <input type="checkbox" checked={none} onChange={(e) => onChange(e.target.checked ? UNITLESS : "")} />
        No unit (just numbers)
      </label>
    </div>
  );
}
