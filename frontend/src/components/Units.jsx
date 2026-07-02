// Unit selector for the x variable: a combobox of common units that also
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
      <span className="units-label">Unit for x (optional)</span>
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
