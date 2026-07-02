// Column-mapping UI. Encodes SurPyval's input rules:
//   - 'x' is mutually exclusive with the 'xl'/'xr' interval pair
//   - 'xl' and 'xr' must be used together
//   - c/n/tl/tr are optional modifiers
const FIELD_INFO = {
  x: { label: "x", help: "Observed values (exact / censored)" },
  c: { label: "c", help: "Censor flag: 0 obs, 1 right, -1 left, 2 interval" },
  n: { label: "n", help: "Count of observations per row" },
  xl: { label: "xl", help: "Interval lower bound (with xr)" },
  xr: { label: "xr", help: "Interval upper bound (with xl)" },
  tl: { label: "tl", help: "Left truncation bound" },
  tr: { label: "tr", help: "Right truncation bound" },
};

const GROUPS = [
  { title: "Variable — use x, or both xl and xr", fields: ["x", "xl", "xr"] },
  { title: "Modifiers", fields: ["c", "n", "tl", "tr"] },
];

export default function ColumnMapper({ columns, mapping, onChange }) {
  const usingX = !!mapping.x;
  const usingInterval = !!mapping.xl || !!mapping.xr;

  const isDisabled = (field) => {
    if (field === "x") return usingInterval;
    if (field === "xl" || field === "xr") return usingX;
    return false;
  };

  const setField = (field, value) => {
    const next = { ...mapping, [field]: value };
    // Enforce mutual exclusivity by clearing the conflicting side.
    if (field === "x" && value) {
      next.xl = "";
      next.xr = "";
    } else if ((field === "xl" || field === "xr") && value) {
      next.x = "";
    }
    onChange(next);
  };

  return (
    <div className="mapper">
      {GROUPS.map((group) => (
        <div className="map-group" key={group.title}>
          <div className="map-group-title">
            <span>{group.title}</span>
          </div>
          <div className="map-fields">
            {group.fields.map((field) => {
              const info = FIELD_INFO[field];
              const disabled = isDisabled(field);
              const selected = !!mapping[field];
              const required = field === "x" || field === "xl" || field === "xr";
              return (
                <label
                  className={
                    "map-field" +
                    (disabled ? " disabled" : "") +
                    (selected ? " selected" : "")
                  }
                  key={field}
                  htmlFor={`map-${field}`}
                  title={`${info.label}${required ? " (required)" : ""} — ${info.help}`}
                >
                  <span className="map-badge">
                    {info.label}
                    {required && <i className="req">*</i>}
                  </span>
                  <div className="select-wrap">
                    <select
                      id={`map-${field}`}
                      aria-label={`${info.label} — ${info.help}`}
                      value={mapping[field] || ""}
                      disabled={disabled}
                      onChange={(e) => setField(field, e.target.value)}
                    >
                      <option value="">— none —</option>
                      {columns.map((col) => (
                        <option value={col} key={col}>
                          {col}
                        </option>
                      ))}
                    </select>
                  </div>
                </label>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
