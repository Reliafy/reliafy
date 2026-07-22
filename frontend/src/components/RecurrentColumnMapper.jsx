import Select from "./Select.jsx";
// Column-mapping UI for recurrent-event (repairable-system) data — the same
// grouped look as the life-data ColumnMapper. Required: i (system id) and x
// (event time). Optional modifiers mirror SurPyval's surface: c/n/tl/tr, where
// tr is each system's observation window (right truncation).
const FIELD_INFO = {
  i: { label: "i", help: "System / unit id — groups events by machine", req: true },
  x: { label: "x", help: "Event time (failure / repair)", req: true },
  c: { label: "c", help: "Censor flag: 0 event, 1 right, -1 left" },
  n: { label: "n", help: "Count of events per row" },
  tl: { label: "tl", help: "Left truncation — observation start / left entry" },
  tr: { label: "tr", help: "Right truncation — each system's observation window" },
};

const COMMON_UNITS = [
  "Hours", "Days", "Weeks", "Months", "Years",
  "Cycles", "Kilometres", "Miles", "Operations", "Rounds",
];

const GROUPS = [
  { title: "Event — system and time", fields: ["i", "x"], cols: 2 },
  { title: "Modifiers (optional)", fields: ["c", "n", "tl", "tr"], cols: 4 },
];

export default function RecurrentColumnMapper({ columns, mapping, onChange, unit, onUnitChange }) {
  const setField = (field, value) => onChange({ ...mapping, [field]: value });

  return (
    <div className="mapper">
      {GROUPS.map((group) => {
        // The unit of the time axis sits inline with the required i/x row.
        const withUnit = group.fields.includes("x") && !!onUnitChange;
        return (
          <div className="map-group" key={group.title}>
            <div className="map-group-title">
              <span>{group.title}</span>
            </div>
            <div className="map-fields" data-cols={withUnit ? group.cols + 1 : group.cols}>
              {group.fields.map((field) => {
                const info = FIELD_INFO[field];
                const selected = !!mapping[field];
                return (
                  <label
                    className={"map-field" + (selected ? " selected" : "")}
                    key={field}
                    htmlFor={`recmap-${field}`}
                    title={`${info.label}${info.req ? " (required)" : ""} — ${info.help}`}
                  >
                    <span className="map-badge">
                      {info.label}
                      {info.req && <i className="req">*</i>}
                    </span>
                    <Select
                      className="sel-embedded"
                      value={mapping[field] || ""}
                      onChange={(v) => setField(field, v)}
                      options={[{ value: "", label: "— none —" }, ...columns]}
                    />
                  </label>
                );
              })}
              {withUnit && (
                <label className="map-field map-unit" title="Unit of the time axis (optional)">
                  <span className="map-badge">unit</span>
                  <input
                    className="map-unit-input"
                    list="rec-units"
                    value={unit || ""}
                    placeholder="e.g. Hours"
                    onChange={(e) => onUnitChange(e.target.value)}
                  />
                  <datalist id="rec-units">
                    {COMMON_UNITS.map((u) => (
                      <option value={u} key={u} />
                    ))}
                  </datalist>
                </label>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
